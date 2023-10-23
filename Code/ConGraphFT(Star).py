import getopt
import math
import sys
import GlobalSensitivity as GlobalSensitivity
import random
import time
import os
import psycopg2
from datetime import datetime
from tqdm import tqdm

# This file is used to return the result for the baseline of ConGraphDP
# Fix tau

def LapNoise():
    a = random.uniform(0, 1)
    b = math.log(1/(1-a))
    c = random.uniform(0, 1)
    if c > 0.5:
        return b
    else:
        return -b
    
class ConGraphFT:
    def __init__(self, epsilon, beta, tau, T, query_name, query=""):
        # Initialize the relation instance used in the temporal experimental:
        self.relations_instance = self.Relations_Instance(epsilon, query_name, tau)
        self.delta_relations_instance = self.Delta_Relations_Instance(epsilon, query_name, tau)
        self.count_relations_instance = self.Count_Relations_Instance(epsilon, query_name, tau)
        self.single_relations_instance = self.Single_Relations_Instance(epsilon, query_name, tau)
        # Initialize the parameter
        self.epsilon = epsilon/relation_nums
        self.beta = beta
        self.T = T
        self.query_name = query_name
        self.query = self.Query_Instance(query)

        # Initialize the other parameter
        self.t = 0
        self.last_t = 0

        self.boundaries = self.Boundaries()
        self.tau = {}
        self.nodes_degree = {}
        for boundary in self.boundaries:
            self.tau[boundary] = tau
            self.nodes_degree[boundary] = {}

        self.con, self.cur = self.ConnectPsql()
        self.CreateTables()
        
    def Relations_Instance(self, epsilon, query_name, tau):
        relations_instance = []
        for num in range(1, relation_nums+1):
            relations_instance.append("%s_fixtau_%s_rounds_%s_r%s"%(query_name, tau, rounds, num))
        return relations_instance

    def Delta_Relations_Instance(self, epsilon, query_name, tau):
        delta_relations_instance = []
        for num in range(1, relation_nums+1):
            delta_relations_instance.append("%s_fixtau_%s_rounds_%s_delta_r%s"%(query_name, tau, rounds, num))
        return delta_relations_instance
    
    def Count_Relations_Instance(self, epsilon, query_name, tau):
        count_relations_instance = []
        for num in range(1, relation_nums+1):
            count_relations_instance.append("%s_fixtau_%s_rounds_%s_count_r%s"%(query_name, tau, rounds, num))
        return count_relations_instance
    
    def Single_Relations_Instance(self, epsilon, query_name, tau):
        single_relations_instance = []
        for num in range(1, relation_nums+1):
            single_relations_instance.append("%s_fixtau_%s_rounds_%s_single_r%s"%(query_name, tau, rounds, num))
        return single_relations_instance

    def Query_Instance(self, query):
        if self.query_name == "three_star":
            query_instance = "select SUM(1.0 * r1.count * r2.count * r3.count)::BIGINT as total\
                                from r1\
                                join r2 on r1.from_id = r2.from_id\
                                join r3 on r1.from_id = r3.from_id;"
        elif self.query_name == "four_star":
            query_instance = "select SUM(1.0 * r1.count * r2.count * r3.count * r4.count)::BIGINT as total\
                                from r1\
                                join r2 on r1.from_id = r2.from_id\
                                join r3 on r1.from_id = r3.from_id\
                                join r4 on r1.from_id = r4.from_id;"
        for num in range(1, relation_nums+1):
            query_instance = query_instance.replace("r%s"%num, self.count_relations_instance[num-1])
        return query_instance
    
    def UpdateNodesDegree(self, from_id, to_id):
        for boundary in self.boundaries:
            if boundary[1] == 'from':
                if from_id in self.nodes_degree[boundary].keys():
                    self.nodes_degree[boundary][from_id] += 1
                else:
                    self.nodes_degree[boundary][from_id] = 1
            elif boundary[1] == 'to':
                if to_id in self.nodes_degree[boundary].keys():
                    self.nodes_degree[boundary][to_id] += 1
                else:
                    self.nodes_degree[boundary][to_id] = 1
    
    def Graph_Clip_Tuples(self, from_id, to_id):
        tuples = [(from_id, to_id)] * relation_nums
        for boundary in self.boundaries:
            # Node denotes the dependency id is from_id or to_id
            orientation = boundary[1] + '_id'
            node = locals()[orientation]
            if self.nodes_degree[boundary][node] < self.tau[boundary]:
                continue
            # The edge is clipped
            else:
                tuples[int(boundary[0]) - 1] = None
        return tuples
    
    def Update(self, from_id, to_id):
        self.t += 1
        self.UpdateNodesDegree(from_id, to_id)
        temp_tuples = self.Graph_Clip_Tuples(from_id, to_id)
        return self.t, temp_tuples
    
    # Get boundaries
    # e.g. triangle query:
    # (1, from), (1, to), (2, from), (2, to), (3, from), (3, to)
    def Boundaries(self):
        boundaries = []
        boudnaries_path = '../Boundary/' + self.query_name + '.txt'
        boundaries_file = open(boudnaries_path, 'r')
        for line in boundaries_file.readlines():
            elements = line.strip().split('|')
            boundaries.append((str(elements[0]), str(elements[1])))
        return boundaries
    
    def ConnectPsql(self):
        con = psycopg2.connect(database = dataset, user=psql_user, password=psql_password, host=psql_host, port=psql_port)
        cur = con.cursor()
        return con, cur
    
    def CreateTables(self):
        for num in range(1, relation_nums+1):
            create_temp_table = "create table %s (timestamp integer not null, from_id integer not null, to_id integer not null)"%self.relations_instance[num-1]
            self.cur.execute(create_temp_table)
            create_delta_table = "create table %s (timestamp integer not null, from_id integer not null, to_id integer not null)"%self.delta_relations_instance[num-1]
            self.cur.execute(create_delta_table)
            create_count_table = "create table %s (from_id integer not null, count integer not null)"%self.count_relations_instance[num-1]
            self.cur.execute(create_count_table)
            create_single_table = "create table %s (from_id integer not null, count integer not null)"%self.single_relations_instance[num-1]
            self.cur.execute(create_single_table)
            self.con.commit()

    def CopyDeltaData(self, intermediate_files=None, tuples=None, type=""):
        if type == "tuple":
            for num in range(1, relation_nums+1):
                if tuples[num-1] == None:
                    continue
                else:
                    insert_delta = "insert into %s values (%s, %s, %s)"%(self.delta_relations_instance[num-1], self.t, tuples[num-1][0], tuples[num-1][1])
                    self.cur.execute(insert_delta)
                    self.con.commit()
                    truncate_single_relation = "truncate table %s"%self.single_relations_instance[num-1]
                    self.cur.execute(truncate_single_relation)
                    self.con.commit()
                    get_single_relation = "insert into %s (from_id, count)\
                                        select from_id, count(from_id)\
                                        from %s\
                                        group by from_id"%(self.single_relations_instance[num-1], self.delta_relations_instance[num-1])
                    self.cur.execute(get_single_relation)
                    self.con.commit()
                    truncate_delta_relation = "truncate table %s"%self.delta_relations_instance[num-1]
                    self.cur.execute(truncate_delta_relation)
                    self.con.commit()
        elif type == "file":
            for num in range(1, relation_nums+1):
                intermediate_files[num-1].seek(0)
                self.cur.copy_from(intermediate_files[num-1], "%s"%self.delta_relations_instance[num-1], sep='|')
                insert_delta = "insert into %s (timestamp, from_id, to_id) select timestamp, from_id, to_id from %s"%(self.relations_instance[num-1], self.delta_relations_instance[num-1])
                self.cur.execute(insert_delta)
                truncate_relation = "truncate table %s"%self.delta_relations_instance[num-1]
                self.cur.execute(truncate_relation)
                self.con.commit()
                intermediate_files[num-1].seek(0)
                intermediate_files[num-1].truncate()

    def DeltaQuery(self, type=None):
        delta_Q = 0
        if type == None:
            # Get count relation information:
            for num in range(1, relation_nums+1):
                truncate_count_relation = "truncate table %s"%(self.count_relations_instance[num-1])
                self.cur.execute(truncate_count_relation)
                self.con.commit()
                get_count_relation = "insert into %s (from_id, count)\
                                        select from_id, count(from_id)\
                                        from %s\
                                        group by from_id"%(self.count_relations_instance[num-1], self.relations_instance[num-1])
                self.cur.execute(get_count_relation)
                self.con.commit()
            delta_query = self.query
            self.cur.execute(delta_query)
            delta_Q = self.cur.fetchone()[0]
            self.con.commit()
            return delta_Q
        elif type == "tuple":
            for num in range(1, relation_nums+1):
                delta_query = self.query.replace(self.count_relations_instance[num-1], self.single_relations_instance[num-1])
                self.cur.execute(delta_query)
                result = self.cur.fetchone()[0]
                if result is None:
                    delta_Q += 0
                else:
                    delta_Q += result
                # Copy current tuple to the count relation
                insert_single = "update %s\
                                set count = %s.count + %s.count\
                                from %s\
                                where %s.from_id = %s.from_id;"%(self.count_relations_instance[num-1],\
                                                                 self.count_relations_instance[num-1],\
                                                                self.single_relations_instance[num-1],\
                                                                self.single_relations_instance[num-1],\
                                                                self.count_relations_instance[num-1],\
                                                                self.single_relations_instance[num-1])
                self.cur.execute(insert_single)
                return delta_Q
    
    def Noise(self, t):
        noise = 0
        simulated_t = t
        simulated_T = self.T
        while simulated_t != 0:
            simulated_t = simulated_t >> 1
            if simulated_t%2 == 1:
                noise += LapNoise() * 1/self.epsilon * math.log(self.T+1, 2) * self.GS_Q()
            else:
                continue 
        writeline = str('GS_Q:%s'%self.GS_Q()) + str(' epsilon:%s'%(self.epsilon)) + str(' log factor:%s'%math.log(self.T+1, 2))
        return noise, writeline
    
    def GS_Q(self):
        GS_method = "GS_Q_" + self.query_name
        GS_Q = getattr(GlobalSensitivity, GS_method)(self.tau)
        return GS_Q

    def RemoveTables(self):
        for num in range(1, relation_nums+1):
            remove_relation = "drop table %s"%self.relations_instance[num-1]
            self.cur.execute(remove_relation)
            remove_delta_relation = "drop table %s"%self.delta_relations_instance[num-1]
            self.cur.execute(remove_delta_relation)
            remove_count_relation = "drop table %s"%self.count_relations_instance[num-1]
            self.cur.execute(remove_count_relation)
            remove_single_relation = "drop table %s"%self.single_relations_instance[num-1]
            self.cur.execute(remove_single_relation)
            self.con.commit()
        self.con.close()

def loaddata(argv):
    global dataset
    dataset = ""
    global query_name
    query_name = ""
    global relation_nums
    relation_nums = 1
    input_file_path = ""
    intermediate_files_prefix = ""
    answer_file_path = ""
    query = ""
    # Privacy budget
    epsilon = 4
    # Error probability: with probability at at least 1-beta, the error can be bounded
    beta = 0.1
    global tau
    tau = 2
    # Experiment round
    global rounds
    rounds = 0
    global psql_user
    psql_user = "postgres"
    global psql_password
    psql_password = "postgres"
    global psql_host
    psql_host = None
    global psql_port
    psql_port = 5432

    try:
        opts, args = getopt.getopt(argv,"d:q:e:b:T:r:u:p:h:o:help:",["dataset=", "query_name=", "epsilon=", "beta=", "tau=", "rounds=", "psql_user=", "psql_password=", "psql_host=", "psql_port", "help="])
    except getopt.GetoptError:
        print("ConGraphFT\(Star\).py -d <dataset> -q <query name> -e <epsilon(default 1)> -T <tau(default 16)> -r <rounds(default 1)> -u <psql_user(default postgres)> -p <psql_password(default postgres)> -h <psql_host(defalut "")>")
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-help':
            print("ConGraphFT\(Star\).py -d <dataset> -q <query name> -e <epsilon(default 1)> -T <tau(default 16)> -r <rounds(default 1)> -u <psql_user(default postgres)> -p <psql_password(default postgres)> -h <psql_host(defalut "")>")
            sys.exit()
        elif opt in ("-d", "--data_name"):
            dataset = str(arg)
        elif opt in ("-q", "--query_name"):
            query_name = str(arg)
            query_file = open('../Query/' + query_name + ".txt", 'r')
            query = ""
            for line in query_file.readlines():
                query += str(line)
            if query_name in ("three_star"):
                relation_nums = 3
            elif query_name in ("four_star"):
                relation_nums = 4
            else:
                print("query_name in wrong domain, please make sure -q being correct")
                sys.exit()
        elif opt in ("-e","--epsilon"):
            epsilon = float(arg)
        elif opt in ("-b","--beta"):
            beta = float(arg)
        elif opt in ("-T", "--tau"):
            tau = int(arg)
        elif opt in ("-r", "--rounds"):
            rounds = int(arg)
        elif opt in ("-u", "--psql_user"):
            psql_user = str(arg)
        elif opt in ("-p", "--psql_password"):
            psql_password = str(arg)
        elif opt in ("-h", "--psql_host"):
            psql_host = str(arg)
        elif opt in ("-o", "--psql_port"):
            psql_port = int(arg)
    currentTime = str(datetime.today().date()) + '-' + datetime.now().strftime("%H-%M-%S")
    input_file_path = "../Temp/" + dataset + '/' + dataset + '.csv'
    intermediate_files_prefix = "../Temp/" + dataset + '/intermediate/' + query_name + '_FixTau_' + str(tau) + '_' + str(rounds) + '_'
    answer_file_path = "../Temp/" + dataset + '/answer/' + query_name + '_FixTau_' + str(tau) + '_' + str(rounds) + '_' + currentTime + '.txt'
    return epsilon, beta, query_name, query, input_file_path, intermediate_files_prefix, answer_file_path

def main(argv):
    start = time.time()
    footsteps = 500000
    epsilon, beta, query_name, query, input_file_path, intermediate_files_prefix, answer_file_path = loaddata(sys.argv[1:])

    intermediate_files = []
    intermediate_files_path = []
    for num in range(1, relation_nums+1):
        intermediate_file_path = intermediate_files_prefix + str(num) + '.txt'
        intermediate_files_path.append(intermediate_file_path)
        intermediate_files.append(open(intermediate_file_path, 'w+'))
    input_file = open(input_file_path, 'r')

    answer_file = open(answer_file_path, 'w')
    
    T = len(input_file.readlines())
    CGFT = ConGraphFT(epsilon, beta, tau, T, query_name, query)
    writeline = "dataset=%s, query_name=%s, epsilon=%s, beta=%s, tau=%s, rounds=%s (FixTau)"%(dataset, query_name, epsilon, beta, tau, rounds) + '\n'
    answer_file.write(writeline)

    res = 0
    res_noise = 0
    input_file.seek(0)
    for line in tqdm(input_file.readlines()):
        elements = line.strip().split('|')
        from_id = int(elements[0])
        to_id = int(elements[1])
        t, temp_tuples = CGFT.Update(from_id, to_id)

        if t % footsteps == 0:
            CGFT.CopyDeltaData(intermediate_files=intermediate_files, type='file')
            res += float(CGFT.DeltaQuery())
            start_timestamp = time.time()
            CGFT.CopyDeltaData(tuples=temp_tuples, type="tuple")
            res += float(CGFT.DeltaQuery(type="tuple"))
            finish_timestamp = time.time()
            noise, writeline = CGFT.Noise(t)
            res_noise = float(res) + noise
            time_length = finish_timestamp - start_timestamp
            writeline = str(t) + '|' + str(res_noise) + '|' + str(time_length) + 's'\
                    + '|' + str(res) + '|' + str(noise) + '|' + writeline
            answer_file.write(writeline + '\n')
        else:
            for num in range(1, relation_nums+1):
                if temp_tuples[num-1] == None:
                    continue
                else:
                    writeline = str(t) + '|' + str(temp_tuples[num-1][0]) + '|' + str(temp_tuples[num-1][1])
                    intermediate_files[num-1].write(str(writeline) + '\n')
    CGFT.RemoveTables()
    input_file.close()
    # Close and remove the intermediate_files
    for num in range(1, relation_nums+1):
        intermediate_files[num-1].close()
        os.remove(intermediate_files_path[num-1])
    end = time.time()
    writeline = "Time=" + str(end - start) + 's'
    answer_file.write(writeline + '\n')
    answer_file.close()
    print("FixTau baseline on dataset: %s with query: %s on tau %s is finished"%(dataset, query_name, tau))

if __name__ == '__main__':
    main(sys.argv[1:])